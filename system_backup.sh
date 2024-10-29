#!/bin/bash

# system_backup.sh
BACKUP_LOG="/var/log/system_backup.log"
BACKUP_PATHS=(
    # System configuration files
    "/etc/nginx"
    "/etc/apache2"
    "/etc/ssh"
    "/etc/network"
    "/etc/wpa_supplicant"
    "/etc/dhcpcd.conf"
    "/etc/hosts"
    "/etc/hostname"
    "/etc/fstab"
    
    # User configuration
    "/home/pi/.bashrc"
    "/home/pi/.config"
    "/home/pi/.local"
    
    # Custom application directories
    "/home/pi/projects"
    "/var/www"
    
    # Service configurations
    "/etc/systemd/system"
    
    # Cron jobs
    "/etc/crontab"
    "/var/spool/cron/crontabs"
    
    # Package lists
    "/var/lib/dpkg/status"
)

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$BACKUP_LOG"
}

# Create a list of installed packages
create_package_list() {
    log_message "Creating package list..."
    dpkg --get-selections > /home/pi/package_list.txt
    apt list --installed > /home/pi/package_versions.txt
}

# Create a list of enabled services
create_service_list() {
    log_message "Creating service list..."
    systemctl list-unit-files --state=enabled > /home/pi/enabled_services.txt
}

# Initialize git repository if it doesn't exist
if [ ! -d "/home/pi/system_backup/.git" ]; then
    log_message "Initializing git repository..."
    mkdir -p /home/pi/system_backup
    cd /home/pi/system_backup || exit
    git init
    
    # Create initial .gitignore
    cat > .gitignore << EOL
# Ignore sensitive files
*.key
*.pem
*id_rsa*
*.password
*.secret
*.conf.bak
*.log
*.cache

# Ignore temporary files
*.tmp
*.temp
*.swp
*.swo
EOL
fi

# Change to backup directory
cd /home/pi/system_backup || exit

# Create package and service lists
create_package_list
create_service_list

# Copy files to backup directory while preserving directory structure
for path in "${BACKUP_PATHS[@]}"; do
    if [ -e "$path" ]; then
        log_message "Backing up $path"
        # Create directory structure
        mkdir -p "/home/pi/system_backup$(dirname "$path")"
        # Copy files while preserving permissions
        cp -rfp "$path" "/home/pi/system_backup$(dirname "$path")/"
    else
        log_message "Warning: $path does not exist"
    fi
done

# Git operations
log_message "Adding files to git..."
git add -A

# Check if there are changes to commit
if git diff --cached --quiet; then
    log_message "No changes to commit"
else
    # Create detailed commit message with system information
    COMMIT_MSG=$(cat << EOL
System backup - $(date '+%Y-%m-%d %H:%M:%S')

System Information:
$(uname -a)

Disk Usage:
$(df -h /)

RAM Usage:
$(free -h)

Temperature:
$(vcgencmd measure_temp)

Changes:
$(git diff --cached --stat)
EOL
)

    # Commit changes
    git commit -m "$COMMIT_MSG"
    
    # Push if remote is configured
    if git remote | grep -q origin; then
        log_message "Pushing changes to remote repository..."
        git push origin main
    else
        log_message "No remote repository configured"
    fi
fi
