#!/bin/bas
set -e

# --- Variables ---
DOTFILES_DIR="/home/alexthiele/nix-config/non-nix"

# --- symlink file mapping ---
source_files=(
  ".config/paperwm/user.js"
)

# ----------------------------------------------------------------------
# DESTINATION PATHS (where the symlinks should be created)
# ----------------------------------------------------------------------
# List the absolute paths in your home directory where the symlinks
# should be created. The order MUST match the source_files array above.
dest_paths=(
  # The location where PaperWM expects to find user.js
  "${HOME}/.config/paperwm/user.js"
)


# --- Install .config---
echo "🚀 Starting to link configuration files..."

for i in "${!source_files[@]}"; do
  source_file="${DOTFILES_DIR}/${source_files[$i]}"
  dest_path="${dest_paths[$i]}"
  
  # Get the directory part of the destination path.
  dest_dir=$(dirname "$dest_path")

  # Create the destination directory if it doesn't already exist.
  # The -p flag ensures that parent directories are also created.
  echo "Ensuring directory exists: ${dest_dir}"
  mkdir -p "$dest_dir"

  # Create the symlink.
  # -s: create a symbolic link
  # -f: force (overwrite) if a symlink already exists at the destination.
  # This makes the script safe to run multiple times.
  echo "Linking ${source_file} -> ${dest_path}"
  ln -sf "$source_file" "$dest_path"
done

echo "✅ Done"

# --- Install apt dependencies ---
echo "🚀 Installing Apt Dependencies..."
bash "${DOTFILES_DIR}/install-apt-deps.sh"
echo "✅ Done"

# --- Install dconf config ---
echo "🚀 Applying Dconf Settings dconf config..."
TIMESTAMP=$(date +%F_%H-%M-%S)
dconf dump / > "${DOTFILES_DIR}/.dconf-backup-${TIMESTAMP}.ini"
dconf load / < "${DOTFILES_DIR}/dconf_gnome_settings.conf"
dconf load / < "${DOTFILES_DIR}/dconf_paperwm_settings.conf"
echo "✅ Done"



