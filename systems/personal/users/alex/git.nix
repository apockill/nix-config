{...}: {
  programs.git = {
    enable = true;
    lfs.enable = true;
    userName = "Alex Thiele";
    userEmail = "apocthiel@gmail.com";
    
    # mark the nix-config as safe
    extraConfig = {
      safe.directory = "/home/alex/dotfiles";
    };
  };
}
