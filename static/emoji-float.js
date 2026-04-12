// Shared emoji float animation — used by participant.html and static/new/code.html
window.showDesktopEmojiFloat = function(emoji, btn) {
  const el = document.createElement('div');
  el.textContent = emoji;
  el.style.cssText = 'position:fixed;font-size:8rem;z-index:10000;pointer-events:none';
  let startX, startY;
  if (btn) {
    const rect = btn.getBoundingClientRect();
    startX = rect.left + rect.width / 2;
    startY = rect.top;
  } else {
    startX = 80;
    startY = window.innerHeight - 100;
  }
  el.style.left = startX + 'px';
  el.style.top = startY + 'px';
  document.body.appendChild(el);

  const duration = 2500 + Math.random() * 1500;
  const riseHeight = 500;
  const driftX = (Math.random() * 2 - 1) * 50;
  const steps = 20;
  const keyframes = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    keyframes.push({
      transform: `translate(calc(-50% + ${t * driftX}px), calc(-50% + ${-riseHeight * t}px)) scale(${1 + t * 0.3})`,
      opacity: t < 0.4 ? 1 : 1 - (t - 0.4) / 0.6,
      offset: t
    });
  }
  const anim = el.animate(keyframes, { duration, easing: 'ease-out', fill: 'forwards' });
  anim.onfinish = () => el.remove();
};
