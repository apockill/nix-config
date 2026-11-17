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
      # A small host-RAM prompt cache. The default (8192 MiB) fills within an hour of every
      # start and then holds ~8 GB of RAM for good (RSS ~23 -> ~31.5 GB), which the box's test
      # runs need. The prompts here are short (p50 ~380, max ~7k tokens), so a cache hit saves
      # a second or two at most. Not 0: without a cache, a slot that takes a new prompt keeps
      # the old one and restores a context checkpoint to reuse the ~13 tokens of chat template,
      # on nearly every request, which was slower and is the path that aborts in b9190 once
      # prompts outgrow the 1024-token SWA window.
      "--cache-ram"
      "1024"
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
