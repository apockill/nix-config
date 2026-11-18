# Local LLM service running llama.cpp with CUDA (sm_87) on the Jetson AGX Orin.
# Serves Gemma 4 26B-A4B for background scheduled jobs with a 256K context window.
#
# llama.cpp comes from nixpkgs-unstable. The release's b9190 aborts restoring a context
# checkpoint into the SWA cache once a few slots are busy with prompts over the 1024-token
# window ("checkpoint size mismatch", ggml-org/llama.cpp#23720, fixed by #23981 in b9473).
# The unstable instance gets jetpack-nixos's nixpkgs arguments, as the system's pkgs does, so
# it builds against the Orin's CUDA (CUDA 12 with cuda_compat, sm_87), not unstable's default.
{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  jetpack = config.hardware.nvidia-jetpack;
  jetpackArgs = inputs.jetpack-nixos.lib.nixpkgsArgsFor {
    inherit (jetpack) majorVersion;
    socType = inputs.jetpack-nixos.lib.socTypeForSom jetpack.som;
  };
  unstable = import inputs.nixpkgs-unstable {
    inherit (pkgs.stdenv.hostPlatform) system;
    inherit (jetpackArgs) overlays;
    config = jetpackArgs.config // {
      cudaSupport = true;
      # The CUDA libraries' licences.
      allowUnfree = true;
      # CUDA 12.9 on JetPack 6's 12.6 driver goes through cuda_compat, as in the system's pkgs.
      # Unlike 26.05, unstable leaves it out unless asked.
      enableCudaDriverCompat = true;
    };
  };
in
{
  services.llama-cpp = {
    enable = true;
    package = unstable.llama-cpp.override { cudaSupport = true; };
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
      # on nearly every request, which was slower.
      "--cache-ram"
      "1024"
      "--alias"
      "gemma-4-26b-a4b"
    ];
  };

  systemd.services.llama-cpp.serviceConfig = {
    # On Jetson AGX Orin, GPU access (/dev/nvmap, /dev/nvhost-*) requires group 'video'
    SupplementaryGroups = [ "video" ];
    TimeoutStartSec = 1800;
    # The module waits 300 s before a restart, 5 min with no local LLM after a crash.
    RestartSec = lib.mkForce 5;
  };
}
