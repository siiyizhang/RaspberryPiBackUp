#!/bin/bash

# system_backup.sh
BACKUP_DIR="/home/siyi/system_backup"
BACKUP_LOG="$BACKUP_DIR/backup.log"
REAL_USER="siyi"

# Ensure backup directory exists and has correct permissions
sudo mkdir -p "$BACKUP_DIR"
sudo chown $REAL_USER:$REAL_USER "$BACKUP_DIR"
sudo chmod 755 "$BACKUP_DIR"

# Initialize log file with correct permissions
sudo touch "$BACKUP_LOG"
sudo chown $REAL_USER:$REAL_USER "$BACKUP_LOG"

BACKUP_PATHS=(
    # Your existing paths here...
    "/etc/nginx"
    "/etc/apache2"
    "/etc/ssh"
    "/etc/network"
    "/etc/wpa_supplicant"
    "/etc/dhcpcd.conf"
    "/etc/hosts"
    "/etc/hostname"
    "/etc/fstab"
    "/home/siyi/.bashrc"
    "/home/siyi/.config"
    "/home/siyi/.local"
    "/home/siyi/projects"
    "/home/siyi/stream.py"
    "/home/siyi/system_backup.sh"
    "/var/www"
    "/etc/systemd/system"
    "/etc/crontab"
    "/var/spool/cron/crontabs"
    "/var/lib/dpkg/status"
)

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$BACKUP_LOG"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Copy files to backup directory
for path in "${BACKUP_PATHS[@]}"; do
    if [ -e "$path" ]; then
        log_message "Backing up $path"
        # Create directory structure
        sudo mkdir -p "$BACKUP_DIR$(dirname "$path")"
        # Copy files only if they don't exist or are different
        sudo rsync -a "$path" "$BACKUP_DIR$(dirname "$path")/"
        # Fix ownership immediately after copying
        sudo chown -R $REAL_USER:$REAL_USER "$BACKUP_DIR$(dirname "$path")"
    else
        log_message "Warning: $path does not exist"
    fi
done

# Save package and service lists with correct permissions
sudo bash -c "dpkg --get-selections > '$BACKUP_DIR/package_list.txt'"
sudo bash -c "systemctl list-unit-files --state=enabled > '$BACKUP_DIR/enabled_services.txt'"
sudo chown $REAL_USER:$REAL_USER "$BACKUP_DIR/package_list.txt"
sudo chown $REAL_USER:$REAL_USER "$BACKUP_DIR/enabled_services.txt"

# Fix permissions for the entire backup directory
sudo chown -R $REAL_USER:$REAL_USER "$BACKUP_DIR"
sudo chmod -R 755 "$BACKUP_DIR"

# Git operations as the real user
sudo -u $REAL_USER bash << EOF
cd "$BACKUP_DIR" || exit
git add -A

if git diff --cached --quiet; then
    echo "No changes to commit"
else
    git commit -m "System backup - $(date '+%Y-%m-%d %H:%M:%S')"
    git push origin main && echo "Changes pushed to GitHub"
fi
EOF
