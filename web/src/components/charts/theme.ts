// Chart colours. The three series colours are the first three slots of the validated categorical palette (checked with the
// dataviz palette validator on a light surface: all checks pass; aqua is under 3:1 contrast, so every chart also has a
// legend and a table view). Series take them in this fixed order.
export const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"] as const;

export const INK = { primary: "#0b0b0b", secondary: "#52514e", muted: "#898781" };
export const GRID = "#e1e0d9"; // hairline gridlines
export const AXIS = "#c3c2b7"; // baseline and axis line
export const SURFACE = "#ffffff"; // card background, used for the ring around dots

export const CHART_HEIGHT = 240; // includes the x-axis labels, so the card never gets its own scrollbar

export const TICK = { fill: INK.muted, fontSize: 12 };
