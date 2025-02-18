{...}: {
  # Set up default bash aliases
  programs.bash.shellAliases = {
    # Kill and delete all containers that don't have the name 'box' in the name.
    # This prevents distrobox or toolbox containers from being accidentally deleted.
    docker-killall = ''
      echo "Removing non-distrobox containers..." && \
      docker container stop $(docker ps -aq --filter "ancestor=$(docker images --format "{{.Repository}}" | grep -v 'box')") && \
      docker container rm $(docker ps -aq --filter "ancestor=$(docker images --format "{{.Repository}}" | grep -v 'box')")
    '';
    edit = "gnome-text-editor";
    dbe = "distrobox enter";
  };

}
