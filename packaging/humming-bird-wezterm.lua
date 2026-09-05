-- App-local configuration. Never reads or rewrites the user's wezterm.lua.
local wezterm = require 'wezterm'
return {
  enable_kitty_keyboard = true,
  check_for_updates = false,
  automatically_reload_config = false,
  initial_cols = 120,
  initial_rows = 38,
  font = wezterm.font('Menlo'),
  font_size = 12.0,
  line_height = 1.0,
  cell_width = 1.0,
  colors = { background = '#000000', foreground = '#c4c4c4' },
  window_background_opacity = 1.0,
  text_background_opacity = 1.0,
  enable_tab_bar = false,
  window_padding = { left = 10, right = 10, top = 8, bottom = 8 },
  audible_bell = 'Disabled',
  exit_behavior = 'Close',
  set_environment_variables = { COLORTERM = 'truecolor' },
}
