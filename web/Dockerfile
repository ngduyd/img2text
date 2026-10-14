# img2text web image (Lane CICD Task 2): vite build → nginx serve SPA.
# Build context là repo ROOT (cần package-lock + web/); /api edge proxy
# nằm ở deploy/nginx.conf (compose stack) — image này serve static SPA thôi.
FROM node:20-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npx vite build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
