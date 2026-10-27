# Production image for the built frontend: static files plus an /api proxy. The development workflow
# (docker-compose.yml, Vite dev server) is unchanged.
#
#   docker build -t awoc-frontend frontend
#   docker run -p 127.0.0.1:8088:8080 -e API_UPSTREAM=http://backend:8000 \
#     -e OIDC_ORIGIN=https://idp.example.org awoc-frontend
#
# Serves plain HTTP on 8080; TLS terminates in front of it.

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
# Where /api requests go, and the identity provider origin the browser may call (token and discovery requests).
ENV API_UPSTREAM=http://backend:8000 \
    OIDC_ORIGIN=http://localhost:8081
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
