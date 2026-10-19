# Video out to the desk projector (a Magcubic HY300 on the DisplayPort
# output, through a DP-to-HDMI cable). The AGX Orin dev kit's DisplayPort is
# its only video output. With kernel modesetting, nvidia-drm exposes that
# port as a DRM connector, so programs running as hermes (group video) can
# drive the projector through /dev/dri.
{ ... }:
{
  hardware.nvidia-jetpack.modesetting.enable = true;
}
