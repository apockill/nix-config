# Local LLM service running llama.cpp with CUDA (sm_87) on the Jetson AGX Orin.
# Serves Gemma 4 26B-A4B for background scheduled jobs with a 256K context window.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  services.llama-cpp = {
    enable = true;
    package = pkgs.llama-cpp.override { cudaSupport = true; };
    host = "127.0.0.1";
    port = 8080;
    extraFlags = [
      "-hf"
      "unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M"
      "-c"
      "262144"
      "-ctk"
      "q8_0"
      "-ctv"
      "q8_0"
      "-ngl"
      "999"
      "-fa"
      "on"
      "--alias"
      "gemma-4-26b-a4b"
    ];
  };

  # On Jetson AGX Orin, GPU access (/dev/nvmap, /dev/nvhost-*) requires group 'video'
  systemd.services.llama-cpp.serviceConfig = {
    SupplementaryGroups = [ "video" ];
    TimeoutStartSec = 1800;
  };
}
