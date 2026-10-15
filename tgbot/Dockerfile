# Сборка: go.mod требует свежий Go, поэтому разрешаем скачать нужный toolchain (GOTOOLCHAIN=auto).
FROM golang:1.24-alpine AS build
ENV GOTOOLCHAIN=auto CGO_ENABLED=0
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -trimpath -ldflags="-s -w" -o /out/tgbot ./cmd/bot

# static-образ с корневыми сертификатами (нужны для api.telegram.org), без оболочки, не root
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/tgbot /tgbot
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/tgbot"]
