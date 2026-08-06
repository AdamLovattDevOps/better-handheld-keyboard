#!/usr/bin/env python3
"""Predictive-text engine for Better Handheld Keyboard.

Pure-Python, offline, no daemons. Three sources of evidence, combined as a linear
interpolation of probabilities (see score()):

  corpus unigram   how common the word is in general
  corpus bigram    how likely the word is right after the previous word
  personal unigram what YOU type
  personal bigram  what YOU type after a given word

Personal evidence carries half the total mass, so the keyboard adapts to your own
vocabulary within a handful of uses instead of being permanently outvoted by a
web-scale corpus (your friends' names, "gamescope", "Legion", ...).

Corpus data lives in ~/.local/share/handheld-kbd/ as two compact text files built
by `handheld-kbd-build-dict`. Personal data is learned.json in the same directory,
saved lazily (debounced) so we never block a keystroke on disk I/O.

The module degrades rather than fails: with no corpus files it still works purely
from what you've typed, and with no data at all suggest() just returns [].
"""
import os, json, math, time, bisect, tempfile

DATA_DIR = os.path.expanduser("~/.local/share/handheld-kbd")

# Interpolation weights. Personal sources get half the mass on purpose (see above);
# within each half, the context-aware (bigram) source outweighs the context-free one.
W_UNI, W_BI, W_PUNI, W_PBI = 0.18, 0.32, 0.18, 0.32

# A correction (the word is not a prefix-extension of what was typed) is multiplied
# by this, so a correction only wins when it is *far* more likely than the literal
# typing. Adjacent-key slips are treated as much more plausible than random ones.
PENALTY_ADJACENT = 0.06     # 'helli' -> 'hello'  (i and o are neighbours)
PENALTY_FAR = 0.004         # unrelated substitution / insertion / deletion

# Extending a corrected stem assumes both a typo and the unseen remainder, so it is
# damped relative to offering the correction itself.
W_CORRECTED_STEM = 0.25
# What you literally typed, when it is a real word, gets a slight edge over longer
# completions of it — you are more often finished than mid-word.
W_EXACT = 1.6

MAX_MEMO = 4000             # bounded prefix->candidates cache
SAVE_DEBOUNCE_S = 20.0      # coalesce learned.json writes


def _atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


def _load_profanity_filter():
    """Optional: keep the suggestion row from proposing slurs and porn vocabulary.

    Suggestions appear unbidden in whatever you are typing into, and a web-scraped
    frequency list contains plenty you would not want offered. The wordlist belongs to a
    library, not to this project — install one and it is used automatically:

        pip install --user better-profanity

    Without it, nothing is filtered and typing is unaffected either way; this never blocks
    you from typing a word, it only decides what gets *offered*.
    """
    import os
    import sys
    # where handheld-kbd-install-filter (or the installer, from the release bundle) puts it
    local = os.path.expanduser("~/.local/lib/handheld-kbd")
    if os.path.isdir(local) and local not in sys.path:
        sys.path.insert(0, local)
    try:
        from better_profanity import profanity
    except Exception:
        return None
    try:
        profanity.load_censor_words()
    except Exception:
        return None
    return lambda w: profanity.contains_profanity(w)


_is_profane = _load_profanity_filter()


def _safe_drop(fn, word):
    try:
        return bool(fn(word))
    except Exception:
        return False


class Predictor:
    def __init__(self, data_dir=DATA_DIR, neighbours=None, max_words=0,
                 filter_profanity=True):
        self.dir = data_dir
        # Only governs what the suggestion row offers; typing is never restricted. Needs an
        # installed profanity library (see _load_profanity_filter) or it is a no-op.
        self.filter_profanity = filter_profanity
        self.words = []          # sorted, lowercase
        self.counts = []         # parallel to words
        self.uni = {}            # word -> count
        self.uni_total = 1
        self.bi = {}             # prev -> {word: count}
        self.bi_total = {}       # prev -> sum of its counts
        self.pu = {}             # personal unigram
        self.pu_total = 0
        self.pbi = {}            # personal bigram
        self.pbi_total = {}
        self.neigh = neighbours or {}   # char -> set(adjacent chars), from the real layout
        self._memo = {}
        self._dirty = False
        self._last_save = 0.0
        self._load_corpus(max_words)
        self._load_personal()

    # ---------- loading ----------
    def _load_corpus(self, max_words):
        try:
            with open(os.path.join(self.dir, "unigrams.txt")) as f:
                for line in f:
                    w, _, c = line.partition("\t")
                    if not c:
                        continue
                    try: n = int(c)
                    except ValueError: continue
                    self.uni[w] = n
                    if max_words and len(self.uni) >= max_words:
                        break
        except Exception:
            pass
        self.words = sorted(self.uni)
        self.counts = [self.uni[w] for w in self.words]
        self.uni_total = sum(self.counts) or 1
        try:
            with open(os.path.join(self.dir, "bigrams.txt")) as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) != 3:
                        continue
                    a, b, c = parts
                    try: n = int(c)
                    except ValueError: continue
                    self.bi.setdefault(a, {})[b] = n
        except Exception:
            pass
        self.bi_total = {a: (sum(d.values()) or 1) for a, d in self.bi.items()}

    def _load_personal(self):
        try:
            with open(os.path.join(self.dir, "learned.json")) as f:
                d = json.load(f)
            self.pu = {k: int(v) for k, v in (d.get("uni") or {}).items()}
            self.pbi = {a: {k: int(v) for k, v in m.items()}
                        for a, m in (d.get("bi") or {}).items()}
        except Exception:
            self.pu, self.pbi = {}, {}
        self.pu_total = sum(self.pu.values())
        self.pbi_total = {a: (sum(m.values()) or 1) for a, m in self.pbi.items()}

    @property
    def ready(self):
        return bool(self.words) or bool(self.pu)

    # ---------- learning ----------
    def learn(self, word, prev=None):
        """Record that the user actually committed `word` (after `prev`)."""
        w = (word or "").strip().lower()
        if not w or not w[0].isalpha() or len(w) > 40:
            return
        self.pu[w] = self.pu.get(w, 0) + 1
        self.pu_total += 1
        p = (prev or "").strip().lower()
        if p:
            m = self.pbi.setdefault(p, {})
            m[w] = m.get(w, 0) + 1
            self.pbi_total[p] = self.pbi_total.get(p, 0) + 1
        self._memo.pop(w[:1], None)          # its ranking may have changed
        self._dirty = True

    def maybe_save(self, force=False):
        """Debounced persist. Safe to call on every keystroke."""
        if not self._dirty:
            return
        now = time.time()
        if not force and now - self._last_save < SAVE_DEBOUNCE_S:
            return
        try:
            _atomic_write(os.path.join(self.dir, "learned.json"),
                          json.dumps({"uni": self.pu, "bi": self.pbi}))
            self._dirty = False
            self._last_save = now
        except Exception:
            pass

    # ---------- probability ----------
    def _p(self, w, prev):
        """Interpolated P(w | prev). Missing sources drop out and the remaining
        weights are renormalised, so a word the corpus has never seen is still
        scored fairly on personal evidence alone."""
        parts, tot = 0.0, 0.0
        c = self.uni.get(w)
        if self.uni_total > 1:
            tot += W_UNI
            if c: parts += W_UNI * (c / self.uni_total)
        if prev:
            d = self.bi.get(prev)
            if d:
                tot += W_BI
                n = d.get(w)
                if n: parts += W_BI * (n / self.bi_total[prev])
        if self.pu_total:
            tot += W_PUNI
            n = self.pu.get(w)
            if n: parts += W_PUNI * (n / self.pu_total)
            m = self.pbi.get(prev or "")
            if m:
                tot += W_PBI
                n = m.get(w)
                if n: parts += W_PBI * (n / self.pbi_total[prev])
        if tot <= 0:
            return 0.0
        return parts / tot

    # ---------- candidate generation ----------
    def _completions(self, prefix, limit=60):
        """Indices of corpus words starting with `prefix`, best-first."""
        if not prefix:
            return []
        hit = self._memo.get(prefix)
        if hit is not None:
            return hit
        i = bisect.bisect_left(self.words, prefix)
        idx = []
        n = len(self.words)
        while i < n and self.words[i].startswith(prefix):
            idx.append(i)
            i += 1
        idx.sort(key=lambda k: -self.counts[k])
        idx = idx[:limit]
        if len(self._memo) > MAX_MEMO:
            self._memo.clear()
        self._memo[prefix] = idx
        return idx

    def _adjacent(self, a, b):
        return b in self.neigh.get(a, ())

    def _edits(self, w):
        """Keyboard-aware edit-distance-1 variants, each tagged with how plausible
        the slip is. Substitutions of neighbouring keys (and doubled/dropped letters,
        which are the other common touch-typing slip) count as 'adjacent'."""
        out = {}
        letters = "abcdefghijklmnopqrstuvwxyz'"
        for i in range(len(w)):
            # deletion: user typed an extra character
            cand = w[:i] + w[i + 1:]
            if cand:
                dup = i > 0 and w[i] == w[i - 1]
                out.setdefault(cand, PENALTY_ADJACENT if dup else PENALTY_FAR)
            # substitution
            for c in letters:
                if c == w[i]:
                    continue
                cand = w[:i] + c + w[i + 1:]
                pen = PENALTY_ADJACENT if self._adjacent(w[i], c) else PENALTY_FAR
                if out.get(cand, 0) < pen:
                    out[cand] = pen
            # transposition of neighbouring characters
            if i + 1 < len(w):
                cand = w[:i] + w[i + 1] + w[i] + w[i + 2:]
                if out.get(cand, 0) < PENALTY_ADJACENT:
                    out[cand] = PENALTY_ADJACENT
        # insertion: user dropped a character
        for i in range(len(w) + 1):
            for c in letters:
                cand = w[:i] + c + w[i:]
                prevc = w[i - 1] if i > 0 else ""
                pen = PENALTY_ADJACENT if (prevc and prevc == c) else PENALTY_FAR
                if out.get(cand, 0) < pen:
                    out[cand] = pen
        out.pop(w, None)
        return out

    # ---------- the public call ----------
    def suggest(self, prefix, prev=None, n=3, corrections=True):
        """Ranked suggestions for the word currently being typed.

        prefix "" -> next-word prediction from `prev` alone.
        Returns a list of words, best first, never containing duplicates.
        """
        prefix = (prefix or "").lower()
        prev = (prev or "").lower() or None
        scored = {}
        drop = _is_profane if (_is_profane and self.filter_profanity) else None

        if not prefix:
            # Pure next-word prediction: everything the corpus/personal bigrams
            # have ever seen after `prev`.
            if not prev:
                return []
            pool = set()
            pool.update((self.bi.get(prev) or {}).keys())
            pool.update((self.pbi.get(prev) or {}).keys())
            if drop is not None:
                pool = {w for w in pool if not _safe_drop(drop, w)}
            for w in pool:
                p = self._p(w, prev)
                if p > 0:
                    scored[w] = p
        else:
            for i in self._completions(prefix):
                w = self.words[i]
                p = self._p(w, prev)
                if p > 0:
                    scored[w] = p
            # personal words are not in the corpus list, so scan them too (small)
            for w in self.pu:
                if w.startswith(prefix):
                    p = self._p(w, prev)
                    if p > 0:
                        scored[w] = max(scored.get(w, 0.0), p)
            if corrections and len(prefix) >= 2:
                for cand, pen in self._edits(prefix).items():
                    # The correction itself — only ever offered if it is a real word,
                    # otherwise we would suggest the typo's neighbours as words.
                    if cand in self.uni or cand in self.pu:
                        v = self._p(cand, prev) * pen
                        if v > scored.get(cand, 0.0):
                            scored[cand] = v
                    # ...and the correction used as a stem. Correcting *and* guessing
                    # the rest is a compound assumption, so it is penalised again.
                    for i in self._completions(cand, limit=6):
                        w = self.words[i]
                        v = self._p(w, prev) * W_CORRECTED_STEM * pen
                        if v > scored.get(w, 0.0):
                            scored[w] = v

        # The literal typing always stays reachable: if what you typed is itself a
        # known word, it is never allowed to fall off the list entirely, and it gets
        # a small edge over longer completions of itself ("i" should beat "in").
        if prefix and (prefix in self.uni or prefix in self.pu):
            lit = self._p(prefix, prev) * W_EXACT
            if lit > scored.get(prefix, 0.0):
                scored[prefix] = lit

        ranked = sorted(scored.items(), key=lambda kv: -kv[1])
        out = []
        for w, _ in ranked:
            if drop is not None:
                try:
                    if drop(w):
                        continue
                except Exception:
                    pass
            out.append(w)
            if len(out) >= n:
                break
        return out


# ---- neighbour map helper -------------------------------------------------
def neighbours_from_rows(rows):
    """Build char -> adjacent chars from the OSK's own resolved layout rows, so
    typo correction matches the keyboard actually on screen (staggered QWERTY,
    or whatever else the user has configured).

    `rows` is the OSK's resolved structure: [[(label, kc, kind, shifted, name)...]]
    Only single-character alphabetic labels take part.
    """
    grid = []
    for row in rows:
        cur = []
        for item in row:
            label = (item[0] or "").lower()
            cur.append(label if len(label) == 1 and label.isalpha() else None)
        grid.append(cur)
    neigh = {}
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if not ch:
                continue
            s = neigh.setdefault(ch, set())
            for dr in (-1, 0, 1):
                rr = r + dr
                if not (0 <= rr < len(grid)):
                    continue
                # rows are horizontally staggered, so on the rows above/below look
                # one column wider on each side
                span = (-1, 0, 1) if dr == 0 else (-1, 0, 1)
                for dc in span:
                    cc = c + dc
                    if dr == 0 and dc == 0:
                        continue
                    if 0 <= cc < len(grid[rr]) and grid[rr][cc]:
                        s.add(grid[rr][cc])
    return neigh


if __name__ == "__main__":
    import sys
    p = Predictor()
    print(f"corpus words={len(p.words)} bigram heads={len(p.bi)} "
          f"personal={len(p.pu)} ready={p.ready}")
    args = sys.argv[1:]
    if args:
        prev = args[0] if len(args) > 1 else None
        pre = args[-1]
        print(f"prev={prev!r} prefix={pre!r} -> {p.suggest(pre, prev, n=5)}")
