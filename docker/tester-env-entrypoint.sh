#!/bin/sh
set -eu

# Grocy keeps all mutable state in GROCY_DATAPATH: config.php (required,
# normally copied from config-dist.php), grocy.db and viewcache/.
# A fresh config.php is a copy of config-dist.php so GROCY_* environment
# settings (which outrank config.php) and the upstream defaults both apply.
data_dir="${GROCY_DATAPATH:-/data}"
mkdir -p "$data_dir"
if [ ! -f "$data_dir/config.php" ]; then
    cp /var/www/html/config-dist.php "$data_dir/config.php"
fi
chown -R www-data:www-data "$data_dir"

exec docker-php-entrypoint apache2-foreground
