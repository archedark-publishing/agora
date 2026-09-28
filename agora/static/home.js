// Homepage behavior: owl animation, quickstart copy button, and header reveal.
(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- header appears once the hero is half scrolled away ---
  const header = document.querySelector(".header");
  const hero = document.querySelector(".hero");
  if (header && hero) {
    const onScroll = () => header.classList.toggle("show", window.scrollY > hero.offsetHeight * 0.5);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // --- quickstart copy ---
  const copyBtn = document.getElementById("qs-copy");
  const promptText = document.getElementById("qs-prompt-text");
  if (copyBtn && promptText) {
    const label = copyBtn.querySelector("span");
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(promptText.textContent.trim());
      } catch {
        return;
      }
      copyBtn.classList.add("done");
      label.textContent = "Copied!";
      setTimeout(() => {
        copyBtn.classList.remove("done");
        label.textContent = "Copy prompt";
      }, 1800);
    });
  }

  const owl = document.getElementById("owl");
  if (!owl) return;
  const head = document.getElementById("head");
  const eyes = [...owl.querySelectorAll(".eye")];

  // --- landing: flap while flying in, then settle onto the branch ---
  function settle() {
    owl.classList.remove("flapping");
    owl.classList.add("settle");
    setTimeout(() => {
      owl.classList.remove("settle");
      owl.classList.add("idle");
    }, 700);
  }
  if (reduceMotion) {
    owl.classList.remove("flapping");
    owl.classList.add("idle");
  } else {
    setTimeout(settle, 1500);
  }

  // --- eyes follow the pointer; head turns slightly toward it ---
  let pointerX = null;
  let pointerY = null;
  let framePending = false;
  function track() {
    framePending = false;
    let dxSum = 0;
    for (const eye of eyes) {
      const r = eye.querySelector("circle").getBoundingClientRect();
      const dx = pointerX - (r.left + r.width / 2);
      const dy = pointerY - (r.top + r.height / 2);
      const dist = Math.hypot(dx, dy) || 1;
      const reach = 12 * Math.min(1, dist / 250);
      eye.querySelector(".pupil").setAttribute(
        "transform",
        `translate(${(dx / dist) * reach} ${(dy / dist) * reach})`,
      );
      dxSum += dx;
    }
    const tilt = Math.max(-3, Math.min(3, dxSum / 2 / 120));
    head.style.transform = `rotate(${tilt}deg)`;
  }
  window.addEventListener("pointermove", (e) => {
    pointerX = e.clientX;
    pointerY = e.clientY;
    if (!framePending) {
      framePending = true;
      requestAnimationFrame(track);
    }
  });

  // --- random blinks ---
  function blink() {
    owl.classList.add("blink");
    setTimeout(() => owl.classList.remove("blink"), 200);
    setTimeout(blink, 2500 + Math.random() * 4000);
  }
  setTimeout(blink, 2400);

  if (reduceMotion) return;

  // --- occasional wing ruffle; flap again on click ---
  function ruffle() {
    if (owl.classList.contains("idle")) {
      owl.classList.add("ruffle");
      setTimeout(() => owl.classList.remove("ruffle"), 900);
    }
    setTimeout(ruffle, 9000 + Math.random() * 6000);
  }
  setTimeout(ruffle, 8000);
  owl.addEventListener("click", () => {
    owl.classList.remove("idle");
    owl.classList.add("flapping");
    setTimeout(settle, 900);
  });
})();
