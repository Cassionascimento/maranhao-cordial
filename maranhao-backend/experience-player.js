"use strict";
document.querySelectorAll("[data-player]").forEach(button => {
  button.addEventListener("click", () => {
    const frame = document.createElement("iframe");
    frame.src = button.dataset.player;
    frame.title = "GINGA — Five Moments | Cássio Nascimento";
    frame.allow = "encrypted-media; picture-in-picture; fullscreen";
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.setAttribute("allowfullscreen", "");
    button.replaceWith(frame);
    frame.focus();
  }, {once: true});
});
