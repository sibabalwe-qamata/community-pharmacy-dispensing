# Build the app, then serve the static output from nginx. nginx also proxies /api to
# the API container, so the browser talks to a single origin and CORS never applies.
FROM node:22-alpine AS build

WORKDIR /srv/web

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /srv/web/dist/web/browser /usr/share/nginx/html

EXPOSE 80
