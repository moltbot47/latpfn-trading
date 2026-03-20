"use client";

import { useEffect, useRef } from "react";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  h: number;
  r: number;
  g: number;
  b: number;
  life: number;
  maxLife: number;
  accel: number;
}

export default function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let W: number, H: number, CX: number, CY: number;
    const particles: Particle[] = [];
    const MAX_PARTICLES = 500;
    let animId: number;

    function resize() {
      W = canvas!.width = canvas!.offsetWidth;
      H = canvas!.height = canvas!.offsetHeight;
      CX = W / 2;
      CY = H / 2;
    }

    function spawn() {
      const angle = Math.random() * Math.PI * 2;
      const edgeDist = Math.max(W, H) * (0.5 + Math.random() * 0.3);

      const brightness = Math.random();
      let r: number, g: number, b: number;
      if (brightness < 0.65) {
        const v = 35 + Math.random() * 50;
        r = v; g = v; b = v;
      } else if (brightness < 0.9) {
        const v = 85 + Math.random() * 70;
        r = v; g = v; b = v;
      } else {
        const v = 180 + Math.random() * 75;
        r = v; g = v; b = v;
      }

      particles.push({
        x: CX + Math.cos(angle) * edgeDist,
        y: CY + Math.sin(angle) * edgeDist,
        vx: -Math.cos(angle) * (0.3 + Math.random() * 0.8),
        vy: -Math.sin(angle) * (0.3 + Math.random() * 0.8),
        size: 3 + Math.random() * 5,
        h: 1 + Math.random() * 5,
        r, g, b,
        life: 0,
        maxLife: 200 + Math.random() * 300,
        accel: 1.003 + Math.random() * 0.004,
      });
    }

    function update() {
      ctx!.fillStyle = "rgba(12, 12, 12, 0.12)";
      ctx!.fillRect(0, 0, W, H);

      for (let s = 0; s < 3; s++) {
        if (particles.length < MAX_PARTICLES) spawn();
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.life++;
        p.vx *= p.accel;
        p.vy *= p.accel;
        p.x += p.vx;
        p.y += p.vy;

        const dist = Math.sqrt((p.x - CX) ** 2 + (p.y - CY) ** 2);
        const maxDist = Math.max(W, H) * 0.7;
        const scale = 0.2 + (dist / maxDist) * 2;

        const lifeRatio = p.life / p.maxLife;
        let alpha: number;
        if (lifeRatio < 0.1) alpha = lifeRatio / 0.1;
        else if (lifeRatio > 0.7) alpha = (1 - lifeRatio) / 0.3;
        else alpha = 1;
        alpha *= 0.6;

        const bMult = 0.6 + (dist / maxDist) * 0.5;
        const drawW = p.size * scale;
        const drawH = p.h * scale;

        if (alpha > 0.01) {
          ctx!.fillStyle = `rgba(${(p.r * bMult) | 0},${(p.g * bMult) | 0},${(p.b * bMult) | 0},${alpha})`;
          ctx!.fillRect(p.x - drawW / 2, p.y - drawH / 2, drawW, drawH);
        }

        if (p.life > p.maxLife || p.x < -50 || p.x > W + 50 || p.y < -50 || p.y > H + 50) {
          particles.splice(i, 1);
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
