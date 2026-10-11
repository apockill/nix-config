{ ... }: {
  programs.git = {
    enable = true;
    lfs.enable = true;
    settings = {
      user.name = "Alex Thiele";
      user.email = "apocthiel@gmail.com";
      safe.directory = "/home/alex/dotfiles";
    };
  };
}
