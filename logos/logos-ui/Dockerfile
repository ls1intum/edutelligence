# logos-ui/Dockerfile
FROM nginx:alpine

# Copy your static files
COPY index.html   /usr/share/nginx/html/
COPY app.js       /usr/share/nginx/html/

# Expose the internal port
EXPOSE 80

# Start nginx (will use default.conf provided by the root nginx)
CMD ["nginx", "-g", "daemon off;"]
