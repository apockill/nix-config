{...}: {
  # Set up default bash aliases
  programs.bash.shellAliases = {
    docker-killall = "docker container stop $(docker container ls -aq) && docker container rm $(docker container ls -aq)";
  };

}
