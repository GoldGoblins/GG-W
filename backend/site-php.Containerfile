FROM registry.fedoraproject.org/fedora:latest
RUN dnf install -y php-cli php-mysqlnd php-json php-mbstring php-xml \
    && dnf clean all
COPY site_php_router.php /gg-router.php
RUN chmod 0644 /gg-router.php
WORKDIR /var/www/html
