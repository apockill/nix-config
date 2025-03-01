{...}: {
  # Set up default bash aliases
  programs.bash.shellAliases = {
    # Kill and delete all containers that don't have the name 'box' in the name.
    # This prevents distrobox or toolbox containers from being accidentally deleted.
    docker-killall = ''
      echo "Stopping non-distrobox containers..." && \
      docker ps -a --format '{{.ID}} {{.Image}}' | grep -v 'box' | awk '{print $1}' | xargs -r docker container stop && \
      echo "Removing non-distrobox containers..." && \
      docker ps -a --format '{{.ID}} {{.Image}}' | grep -v 'box' | awk '{print $1}' | xargs -r docker container rm && \
      echo "Done!"
    '';
    edit = "gnome-text-editor";
    dbe = "distrobox enter";
  };
}
