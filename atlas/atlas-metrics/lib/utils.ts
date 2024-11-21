import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function generateColor(index: number) {
  const hue = (index * 137.5) % 360; // 137.5 is the golden angle in degrees
  return `hsl(${hue}, 70%, 50%)`;
};