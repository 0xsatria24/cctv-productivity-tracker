import tokens from '../../docs/ui/design-tokens.json';

export function installTheme() {
  const root = document.documentElement;
  Object.entries(tokens.colors).forEach(([key, value]) => root.style.setProperty(`--${key.replaceAll('.', '-')}`, value));
  for (const [group, prefix] of [['spacing', 'space'], ['radius', 'radius'], ['stroke', 'stroke']]) {
    Object.entries(tokens[group]).forEach(([key, value]) => root.style.setProperty(`--${prefix}-${key}`, `${value}px`));
  }
  Object.entries(tokens.fonts.roles).forEach(([key, value]) => root.style.setProperty(`--font-${key}`, `${value.point_size * 4 / 3}px`));
}
