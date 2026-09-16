FROM node:22-alpine AS build

ARG VITE_INFERENCE_WS_URL=ws://localhost:8000/ws/inference
ARG VITE_INFERENCE_HTTP_URL=http://localhost:8000
ENV VITE_INFERENCE_WS_URL=$VITE_INFERENCE_WS_URL \
    VITE_INFERENCE_HTTP_URL=$VITE_INFERENCE_HTTP_URL

WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
COPY contracts /contracts
RUN npm run build

FROM nginx:1.27-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
