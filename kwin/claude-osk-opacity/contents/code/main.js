function setOp(w){
    try {
        var c = "" + w.resourceClass;
        var cap = "" + w.caption;
        if (c.indexOf("claude-osk") !== -1) w.opacity = 0.72;
        else if (cap.indexOf("Steam Input On-screen Keyboard") !== -1) w.opacity = 0.0;
    } catch(e){}
}
workspace.windowList().forEach(setOp);
workspace.windowAdded.connect(setOp);
