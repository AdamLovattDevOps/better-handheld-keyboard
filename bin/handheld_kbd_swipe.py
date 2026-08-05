#!/usr/bin/env python3
"""Glide/swipe typing decoder for Better Handheld Keyboard.

Given the path a finger traced across the keys, work out which word was meant.
This is the SHARK²/ShapeWriter approach (Kristensson & Zhai, UIST 2004), reduced
to what runs comfortably in pure Python on a handheld:

  1. Candidates come from an index keyed on (first letter, last letter). The ends
     of a swipe are the parts the user aims at deliberately, so they are by far the
     most reliable signal — and it turns a 80k-word scan into a few hundred.
  2. A path-length prior throws out words whose ideal gesture is much longer or
     shorter than what was actually drawn. This is nearly free and prunes hard.
  3. Survivors are scored coarsely (10 sample points), and only the best of those
     are scored finely (32 points) on two channels:
        location — how close the drawn path sits to the word's ideal path
        shape    — how similar they are after normalising away position and scale
     Location alone confuses words on the same keys; shape alone confuses words
     that trace the same figure elsewhere on the keyboard. Together they don't.
  4. The language model (the same Predictor the suggestion row uses, including
     everything it has learned about your vocabulary) breaks the remaining ties.

Returns a ranked list, so the caller can type the best word and offer the rest.
"""
import math

N_COARSE = 10          # sample points for the cheap first pass
N_FINE = 24            # sample points for the real comparison
COARSE_KEEP = 30       # candidates promoted to fine scoring

LEN_LO, LEN_HI = 0.5, 2.0     # allowed ideal/drawn path-length ratio

W_SHAPE = 0.5          # weight of the shape channel relative to location
W_END = 0.8            # weight of the endpoint channel (see below)
W_LM = 0.9             # how much the language model may move a geometric verdict
MIN_LEN = 2            # words shorter than this are tapped, not swiped


def _resample(pts, n):
    """Uniformly re-sample a polyline to exactly n points by arc length."""
    if not pts:
        return []
    if len(pts) == 1:
        return [pts[0]] * n
    acc = [0.0]
    for i in range(1, len(pts)):
        acc.append(acc[-1] + math.dist(pts[i - 1], pts[i]))
    total = acc[-1]
    if total <= 1e-9:
        return [pts[0]] * n
    out, step, j = [], total / (n - 1), 0
    for i in range(n):
        target = i * step
        while j < len(acc) - 2 and acc[j + 1] < target:
            j += 1
        seg = acc[j + 1] - acc[j]
        t = 0.0 if seg <= 1e-9 else (target - acc[j]) / seg
        ax, ay = pts[j]
        bx, by = pts[j + 1]
        out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


def _smooth(pts, window=5):
    """Moving average over the raw touch samples.

    Finger jitter is small per sample but it accumulates: measured against a clean
    polyline, raw samples of a swipe can be 30-75% longer than the gesture actually
    drawn, which wrecks both the length prior and the shape comparison. Smoothing
    first makes the drawn path comparable to a word's ideal path.
    """
    n = len(pts)
    if n <= window:
        return list(pts)
    half = window // 2
    out = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        seg = pts[lo:hi]
        k = len(seg)
        out.append((sum(p[0] for p in seg) / k, sum(p[1] for p in seg) / k))
    return out


def _polyline_len(pts):
    return sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def _chamfer(a, b):
    """Symmetric mean nearest-neighbour distance between two point sets.

    Preferred over comparing samples index-by-index, because that assumes both
    paths were traversed at the same rate. Real swipes cut corners and slow down
    at direction changes, which shifts the index correspondence and punishes the
    correct word. Nearest-point matching doesn't care how the path was timed.
    """
    s1 = sum(min(math.dist(p, q) for q in b) for p in a) / len(a)
    s2 = sum(min(math.dist(q, p) for p in a) for q in b) / len(b)
    return 0.5 * (s1 + s2)


def _normalise(pts):
    """Translate to centroid and scale to unit RMS radius, so two paths can be
    compared on shape alone."""
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    cen = [(p[0] - cx, p[1] - cy) for p in pts]
    r = math.sqrt(sum(x * x + y * y for x, y in cen) / n)
    if r < 1e-9:
        return cen
    return [(x / r, y / r) for x, y in cen]


class SwipeDecoder:
    def __init__(self, predictor):
        self.pred = predictor
        self.centers = {}      # char -> (x, y) in grid coordinates
        self.key_w = 1.0
        self._buckets = {}     # (first, last) -> [word]
        self._vocab_key = None

    # ---- setup -----------------------------------------------------------
    def set_keys(self, centers, key_w):
        """Tell the decoder where the letter keys currently are."""
        self.centers = dict(centers)
        self.key_w = max(1.0, float(key_w))
        self._rebuild_index()

    def _rebuild_index(self):
        """Index the vocabulary by (first, last) letter. Rebuilt only when the
        vocabulary or the available keys actually change."""
        vocab_key = (len(getattr(self.pred, "words", ())),
                     len(getattr(self.pred, "pu", ())),
                     "".join(sorted(self.centers)))
        if vocab_key == self._vocab_key:
            return
        self._vocab_key = vocab_key
        keys = set(self.centers)
        buckets = {}
        words = list(getattr(self.pred, "words", ()))
        words += [w for w in getattr(self.pred, "pu", {}) if w not in self.pred.uni]
        for w in words:
            if len(w) < MIN_LEN:
                continue
            if not keys.issuperset(w):
                continue
            buckets.setdefault((w[0], w[-1]), []).append(w)
        self._buckets = buckets

    @property
    def ready(self):
        return bool(self._buckets)

    # ---- decoding --------------------------------------------------------
    def _near_keys(self, pt, radius_mult=0.95):
        """Letter keys whose centre is within radius of a point, nearest first."""
        r = self.key_w * radius_mult
        out = []
        for ch, c in self.centers.items():
            d = math.dist(pt, c)
            if d <= r:
                out.append((d, ch))
        out.sort()
        return [ch for _, ch in out[:4]]

    def _ideal(self, word):
        return [self.centers[c] for c in word]

    def decode(self, path, prev_word=None, n=3):
        """Rank the words that the drawn `path` could be. Best first."""
        if len(path) < 3 or not self._buckets:
            return []
        path = _smooth(path)
        drawn_len = _polyline_len(path)
        if drawn_len < self.key_w * 0.8:
            return []                      # too short to be a gesture

        starts = self._near_keys(path[0]) or []
        ends = self._near_keys(path[-1]) or []
        if not starts or not ends:
            return []

        cands = []
        for s in starts:
            for e2 in ends:
                cands.extend(self._buckets.get((s, e2), ()))
        if not cands:
            return []

        user_coarse = _resample(path, N_COARSE)

        # --- pass 1: length prior, then coarse location cost ---------------
        scored = []
        for w in cands:
            ideal = self._ideal(w)
            ilen = _polyline_len(ideal)
            # a straight two-key word has a short ideal path; guard against /0
            ratio = (ilen + self.key_w) / (drawn_len + self.key_w)
            if ratio < LEN_LO or ratio > LEN_HI:
                continue
            ic = _resample(ideal, N_COARSE)
            cost = sum(math.dist(a, b) for a, b in zip(user_coarse, ic))
            scored.append((cost / (N_COARSE * self.key_w), w))
        if not scored:
            return []
        scored.sort()
        finalists = [w for _, w in scored[:COARSE_KEEP]]

        # --- pass 2: fine location + shape, then the language model ---------
        user_fine = _resample(path, N_FINE)
        user_norm = _normalise(user_fine)
        out = []
        for w in finalists:
            ideal_fine = _resample(self._ideal(w), N_FINE)
            loc = _chamfer(user_fine, ideal_fine) / self.key_w
            ideal_norm = _normalise(ideal_fine)
            shp = sum(math.dist(a, b) for a, b in zip(user_norm, ideal_norm)) / N_FINE
            # Endpoint channel: where a swipe starts and stops is aimed at
            # deliberately, unlike the middle, which is just travel. Without this,
            # a word that ends one key early ("gel" for "hello") scores almost as
            # well as the real one.
            ends = (math.dist(user_fine[0], ideal_fine[0]) +
                    math.dist(user_fine[-1], ideal_fine[-1])) / (2.0 * self.key_w)
            geo = loc + W_SHAPE * shp + W_END * ends
            try:
                p = self.pred._p(w, prev_word)
            except Exception:
                p = 0.0
            lm = math.log10(p) if p > 0 else -12.0
            # lm is about -2 (very common) to -12 (unknown); map to a bounded bonus
            out.append((geo - W_LM * ((lm + 12.0) / 10.0), w))
        out.sort()
        return [w for _, w in out[:n]]
