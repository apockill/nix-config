# Video out to the desk projector (a Magcubic HY300 on the DisplayPort
# output, through a DP-to-HDMI cable). The AGX Orin dev kit's DisplayPort is
# its only video output. With kernel modesetting, nvidia-drm exposes that
# port as a DRM connector, so programs running as hermes (group video) can
# drive the projector through /dev/dri.
#
# Requires the UEFI setting "SOC Display Hand-Off Mode" = Never (UEFI
# variable SocDisplayHandoffMode = 0). It's firmware state, not Nix: a
# reflash can reset it. With Auto/Always, UEFI hands its lit boot screen to
# Linux (simpledrm grabs it as fb0), and nvidia-drm then never gets flip
# completions: "Flip event timeout on head 0", nvidia-modeset hangs in D
# state, and the projector stays dark. NVIDIA: the display driver doesn't
# support hand-off. Check and set it: hosts/ai-box/README.md, Troubleshooting.
{ ... }:
{
  hardware.nvidia-jetpack.modesetting.enable = true;
}
