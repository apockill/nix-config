-- paperlike, an awesome 3 theme by Tyler Compton

--{{{ Main
local awful = require("awful")
awful.util = require("awful.util")

theme = {}

home          = os.getenv("HOME")
config        = awful.util.getdir("config")
shared        = "/usr/share/awesome"
if not awful.util.file_readable(shared .. "/icons/awesome16.png") then
    shared    = "/usr/share/local/awesome"
end
sharedicons   = shared .. "/icons"
sharedthemes  = shared .. "/themes"
themes        = config
themename     = "/paperlike"
if not awful.util.file_readable(themes .. themename .. "/theme.lua") then
       themes = sharedthemes
end
themedir      = themes .. themename

wallpaper1    = themes .. themename .. "/background.jpeg"
wpscript      = home .. "/.wallpaper"

if awful.util.file_readable(wallpaper1) then
  theme.wallpaper = wallpaper1
elseif awful.util.file_readable(wallpaper2) then
  theme.wallpaper = wallpaper2
elseif awful.util.file_readable(wpscript) then
  theme.wallpaper_cmd = { "sh " .. wpscript }
end
--}}}

theme.font          = "Noto Sans 8"

theme.bg_normal     = "#242424"
theme.bg_focus      = "#303030"
theme.bg_urgent     = "#006B8E"
theme.bg_minimize   = "#959186"

theme.fg_normal     = "#FFFFFF"
theme.fg_focus      = "#0099CC"
theme.fg_urgent     = "#CC9393"
theme.fg_minimize   = "#eee8d5"

theme.border_width  = "3"
theme.border_normal = "#252525"
theme.border_focus  = "#0099CC"
theme.border_marked = "#052F52FF"

-- Display the taglist squares
theme.taglist_squares_sel   = themedir .. "/taglist/focus.png"
theme.taglist_squares_unsel = themedir .. "/taglist/unfocus.png"

-- Awesome icon
theme.awesome_icon = themedir .. "/awesome-icon.png"

-- Layout icons
theme.layout_fairh = themedir .. "/layouts/fairh.png"
theme.layout_fairv = themedir .. "/layouts/fairv.png"
theme.layout_floating  = themedir .. "/layouts/floating.png"
theme.layout_magnifier = themedir .. "/layouts/magnifier.png"
theme.layout_max = themedir .. "/layouts/max.png"
theme.layout_fullscreen = themedir .. "/layouts/fullscreen.png"
theme.layout_tilebottom = themedir .. "/layouts/tilebottom.png"
theme.layout_tileleft   = themedir .. "/layouts/tileleft.png"
theme.layout_tile = themedir .. "/layouts/tile.png"
theme.layout_tiletop = themedir .. "/layouts/tiletop.png"
theme.layout_spiral  = themedir .. "/layouts/spiral.png"
theme.layout_dwindle = themedir .. "/layouts/dwindle.png"

-- HOLO

icon_dir = themedir .. "/icons"
theme.awesome_icon                              = icon_dir .. "/awesome_icon_white.png"
theme.awesome_icon_launcher                     = icon_dir .. "/awesome_icon.png"
theme.taglist_squares_sel                       = icon_dir .. "/square_sel.png"
theme.taglist_squares_unsel                     = icon_dir .. "/square_unsel.png"
theme.spr_small                                 = icon_dir .. "/spr_small.png"
theme.spr_very_small                            = icon_dir .. "/spr_very_small.png"
theme.spr_right                                 = icon_dir .. "/spr_right.png"
theme.spr_bottom_right                          = icon_dir .. "/spr_bottom_right.png"
theme.spr_left                                  = icon_dir .. "/spr_left.png"
theme.bar                                       = icon_dir .. "/bar.png"
theme.bottom_bar                                = icon_dir .. "/bottom_bar.png"
theme.mpdl                                      = icon_dir .. "/mpd.png"
theme.mpd_on                                    = icon_dir .. "/mpd_on.png"
theme.prev                                      = icon_dir .. "/prev.png"
theme.nex                                       = icon_dir .. "/next.png"
theme.stop                                      = icon_dir .. "/stop.png"
theme.pause                                     = icon_dir .. "/pause.png"
theme.play                                      = icon_dir .. "/play.png"
theme.clock                                     = icon_dir .. "/clock.png"
theme.calendar                                  = icon_dir .. "/cal.png"
theme.cpu                                       = icon_dir .. "/cpu.png"
theme.net_up                                    = icon_dir .. "/net_up.png"
theme.net_down                                  = icon_dir .. "/net_down.png"
theme.layout_tile                               = icon_dir .. "/tile.png"
theme.layout_tileleft                           = icon_dir .. "/tileleft.png"
theme.layout_tilebottom                         = icon_dir .. "/tilebottom.png"
theme.layout_tiletop                            = icon_dir .. "/tiletop.png"
theme.layout_fairv                              = icon_dir .. "/fairv.png"
theme.layout_fairh                              = icon_dir .. "/fairh.png"
theme.layout_spiral                             = icon_dir .. "/spiral.png"
theme.layout_dwindle                            = icon_dir .. "/dwindle.png"
theme.layout_max                                = icon_dir .. "/max.png"
theme.layout_fullscreen                         = icon_dir .. "/fullscreen.png"
theme.layout_magnifier                          = icon_dir .. "/magnifier.png"
theme.layout_floating                           = icon_dir .. "/floating.png"
theme.tasklist_plain_task_name                  = true
theme.tasklist_disable_icon                     = true
theme.useless_gap                               = 0

return theme

