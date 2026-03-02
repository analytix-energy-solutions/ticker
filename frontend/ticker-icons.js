/**
 * Ticker Custom Iconset
 * Registers the Ticker logo as a custom icon for Home Assistant
 * 
 * Usage: ticker:logo
 * 
 * Brand: See branding/README.md
 */

const TICKER_ICONS = {
  logo: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 1.5c4.69 0 8.5 3.81 8.5 8.5s-3.81 8.5-8.5 8.5S3.5 16.69 3.5 12 7.31 3.5 12 3.5zM12 6c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm0 1.5c2.48 0 4.5 2.02 4.5 4.5s-2.02 4.5-4.5 4.5S7.5 14.48 7.5 12 9.52 7.5 12 7.5zm0 2a2.5 2.5 0 100 5 2.5 2.5 0 000-5z",
};

window.customIconsets = window.customIconsets || {};
window.customIconsets["ticker"] = (name) => {
  return {
    path: TICKER_ICONS[name] || TICKER_ICONS.logo,
    viewBox: "0 0 24 24",
  };
};

// Register with Home Assistant's custom icon handler
window.customIcons = window.customIcons || {};
window.customIcons["ticker"] = {
  getIcon: (name) => {
    return {
      path: TICKER_ICONS[name] || TICKER_ICONS.logo,
      viewBox: "0 0 24 24",
    };
  },
};

// Notify Home Assistant that a new iconset is available
const event = new CustomEvent("custom-icon-loaded", {
  detail: { name: "ticker" },
});
window.dispatchEvent(event);
