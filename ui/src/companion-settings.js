export const COLORS = [
  { id: 'teal', name: 'Teal', hex: '#53cdd0', filter: 'none' },
  { id: 'rose', name: 'Rose', hex: '#ee8eb5', filter: 'hue-rotate(155deg)' },
  { id: 'butter', name: 'Butter', hex: '#f2ce71', filter: 'hue-rotate(225deg)' },
  { id: 'peach', name: 'Peach', hex: '#efa483', filter: 'hue-rotate(190deg)' },
  { id: 'lilac', name: 'Lilac', hex: '#bda1e4', filter: 'hue-rotate(95deg)' },
  { id: 'blue', name: 'Blue', hex: '#5b8def', filter: 'hue-rotate(45deg) saturate(1.2)' },
];
export const DEFAULT_SETTINGS = { displayName: 'Ambi', color: 'blue', background: 'navy', scale: .78, animated: true };
export function normalizeSettings(value = {}) {
  value = value && typeof value === 'object' ? value : {};
  const name = typeof value.displayName === 'string' ? value.displayName.trim().slice(0, 24) : '';
  return { displayName: name || 'Ambi', color: COLORS.some(color => color.id === value.color) ? value.color : 'blue',
    background: ['white', 'black', 'navy'].includes(value.background) ? value.background : 'navy',
    scale: typeof value.scale === 'number' && Number.isFinite(value.scale) ? Math.max(.35, Math.min(.95, value.scale)) : .78,
    animated: typeof value.animated === 'boolean' ? value.animated : true };
}
export function colorFilter(id) { return COLORS.find(color => color.id === id)?.filter || 'none'; }
