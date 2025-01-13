{...}: {
  programs.git = {
    enable = true;
    lfs.enable = true;
    userName = "Alex Thiele";
    userEmail = "apocthiel@gmail.com";
    signing = {
      signByDefault = true;
      key = null;
    };
    
    # mark the nix-config as safe
    extraConfig = {
      safe.directory = "/home/ryan/nix-config";
    };
  };
}
