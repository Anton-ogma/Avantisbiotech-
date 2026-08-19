FROM node:20-alpine AS build
WORKDIR /app
# Локфайл копируется вместе с манифестом, и ставится `npm ci`, а не `npm install`:
# `install` свободен подтянуть новые минорные версии, и собранный сегодня образ
# отличается от вчерашнего без единой правки в репозитории.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
# Предел тела по умолчанию совпадает с DIERS_MAX_UPLOAD_MB в API.
ENV MAX_UPLOAD_MB=32
EXPOSE 80
