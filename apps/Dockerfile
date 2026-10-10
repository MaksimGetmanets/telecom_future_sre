# Сборка образа одного сервиса: docker build -f apps/Dockerfile --build-arg MODULE=gateway apps
# Контекст сборки — папка apps/ (нужен родительский pom и модуль common).

FROM maven:3.9-eclipse-temurin-21 AS build
ARG MODULE
ARG OTEL_VERSION=2.10.0
WORKDIR /src
COPY . .
# Кэш ~/.m2 переиспользуется между сборками (нужен BuildKit, в Docker Desktop включён по умолчанию)
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q -pl ${MODULE} -am package -Dmaven.test.skip=true
RUN curl -fsSL -o /opentelemetry-javaagent.jar \
    "https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v${OTEL_VERSION}/opentelemetry-javaagent.jar" \
    && chmod 644 /opentelemetry-javaagent.jar

FROM eclipse-temurin:21-jre
ARG MODULE
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /opentelemetry-javaagent.jar /opt/otel/opentelemetry-javaagent.jar
COPY --from=build /src/${MODULE}/target/${MODULE}.jar /app/app.jar
USER 10001
EXPOSE 8080
# OTel-агент подключается без изменения кода; адрес Tempo задаётся переменными окружения в чарте
ENV JAVA_OPTS="-javaagent:/opt/otel/opentelemetry-javaagent.jar -XX:MaxRAMPercentage=55"
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
