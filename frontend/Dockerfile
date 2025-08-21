# Simple static file server for HTML app
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy static files directly
COPY public/ /usr/share/nginx/html/

# Create placeholder icons if they don't exist
RUN touch /usr/share/nginx/html/icon-192.png || true
RUN touch /usr/share/nginx/html/icon-512.png || true

# Expose port
EXPOSE 3001

# Start nginx
CMD ["nginx", "-g", "daemon off;"]