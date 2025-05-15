# logos-ui/Dockerfile

FROM nginx:alpine

# Kopiere AngularJS-App
COPY ./logos/logos-ui/index.html /usr/share/nginx/html/index.html
COPY ./logos/logos-ui/app.js /usr/share/nginx/html/app.js

# Optional: Custom NGINX config
# COPY ./nginx.conf /etc/nginx/nginx.conf

EXPOSE 8081
