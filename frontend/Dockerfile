FROM node:18-alpine as builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install --only=production

# Copy source code
COPY . .

# Build the app
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built app
COPY --from=builder /app/build /usr/share/nginx/html

# Add PWA files to root
COPY --from=builder /app/public/manifest.json /usr/share/nginx/html/
COPY --from=builder /app/public/sw.js /usr/share/nginx/html/
COPY --from=builder /app/public/icon-*.png /usr/share/nginx/html/

# Expose port
EXPOSE 3000

# Start nginx
CMD ["nginx", "-g", "daemon off;"]