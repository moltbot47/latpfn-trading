"use client";

import { useEffect, useRef } from "react";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  r: number;
  g: number;
  b: number;
  life: number;
  maxLife: number;
}

export default function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let W: number, H: number;
    const particles: Particle[] = [];
    const MAX_PARTICLES = 80;
    let animId: number;

    function resize() {
      W = canvas!.width = canvas!.offsetWidth;
      H = canvas!.height = canvas!.offsetHeight;
    }

    function spawn() {
      // Spawn from random edge
      const side = Math.random();
      let x: number, y: number;
      if (side < 0.25) { x = Math.random() * W; y = -5; }
      else if (side < 0.5) { x = Math.random() * W; y = H + 5; }
      else if (side < 0.75) { x = -5; y = Math.random() * H; }
      else { x = W + 5; y = Math.random() * H; }

      // Drift slowly toward center with slight randomness
      const angle = Math.atan2(H / 2 - y, W / 2 - x) + (Math.random() - 0.5) * 0.8;
      const speed = 0.15 + Math.random() * 0.25;

      const v = 30 + Math.random() * 40;

      particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 1 + Math.random() * 1.5,
        r: v, g: v, b: v,
        life: 0,
        maxLife: 400 + Math.random() * 400,
      });
    }

    function update() {
      ctx!.clearRect(0, 0, W, H);

      // Spawn slowly
      if (particles.length < MAX_PARTICLES && Math.random() < 0.3) {
        spawn();
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.life++;
        p.x += p.vx;
        p.y += p.vy;

        // Fade in/out
        const lifeRatio = p.life / p.maxLife;
        let alpha: number;
        if (lifeRatio < 0.15) alpha = lifeRatio / 0.15;
        else if (lifeRatio > 0.7) alpha = (1 - lifeRatio) / 0.3;
        else alpha = 1;
        alpha *= 0.15; // Very subtle

        if (alpha > 0.005) {
          ctx!.beginPath();
          ctx!.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          ctx!.fillStyle = `rgba(${p.r},${p.g},${p.b},${alpha})`;
          ctx!.fill();
        }

        if (p.life > p.maxLife || p.x < -20 || p.x > W + 20 || p.y < -20 || p.y > H + 20) {
          particles.splice(i, 1);
        }
      }

      // Draw subtle connecting lines between nearby particles
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 150) {
            const lineAlpha = (1 - dist / 150) * 0.06;
            ctx!.beginPath();
            ctx!.moveTo(particles[i].x, particles[i].y);
            ctx!.lineTo(particles[j].x, particles[j].y);
            ctx!.strokeStyle = `rgba(100,100,100,${lineAlpha})`;
            ctx!.lineWidth = 0.5;
            ctx!.stroke();
          }
        }
      }

      animId = requestAnimationFrame(update);
    }

    resize();
    update();
    window.addEventListener("resize", resize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        zIndex: 0,
        pointerEvents: "none",
      }}
    />
  );
}
