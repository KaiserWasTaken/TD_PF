CREATE TABLE IF NOT EXISTS analytics_siniestro (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 fecha_hora DATETIME NOT NULL,
 tipo_siniestro VARCHAR(50) NOT NULL,
 tipo_usuario VARCHAR(50) NOT NULL,
 gravedad ENUM('solo danos','herido','muerto') NOT NULL,
 num_muertos INT UNSIGNED NOT NULL DEFAULT 0,
 num_heridos INT UNSIGNED NOT NULL DEFAULT 0,
 latitud DOUBLE NULL,
 longitud DOUBLE NULL,
 calidad_geo VARCHAR(30) NULL,
 fuente VARCHAR(50) NOT NULL,
 id_origen VARCHAR(100) NULL,
 hash_registro CHAR(64) NOT NULL,
 UNIQUE KEY uq_siniestro_hash (hash_registro),
 INDEX idx_siniestro_fecha (fecha_hora),
 INDEX idx_siniestro_tipo_usuario (tipo_usuario)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS siniestro_georreferencia (
 siniestro_id BIGINT UNSIGNED PRIMARY KEY,
 archivo VARCHAR(255) NOT NULL,
 fila BIGINT UNSIGNED NOT NULL,
 hash_archivo CHAR(64) NOT NULL,
 id_fuente VARCHAR(100) NOT NULL,
 calle1 VARCHAR(255) NULL,
 calle2 VARCHAR(255) NULL,
 FOREIGN KEY (siniestro_id) REFERENCES analytics_siniestro(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_tiempo (
 tiempo_key INT UNSIGNED PRIMARY KEY,
 fecha DATE NOT NULL,
 anio SMALLINT UNSIGNED NOT NULL,
 mes TINYINT UNSIGNED NOT NULL,
 nombre_mes VARCHAR(20) NOT NULL,
 dia_semana VARCHAR(20) NOT NULL,
 es_fin_de_semana BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE KEY uq_dim_tiempo_fecha (fecha)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_hora (
 hora_key TINYINT UNSIGNED PRIMARY KEY,
 franja VARCHAR(30) NOT NULL,
 es_hora_pico BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB;

INSERT IGNORE INTO dim_hora (hora_key, franja, es_hora_pico) VALUES
(0,'madrugada',FALSE),(1,'madrugada',FALSE),(2,'madrugada',FALSE),(3,'madrugada',FALSE),
(4,'madrugada',FALSE),(5,'madrugada',FALSE),(6,'madrugada',FALSE),
(7,'pico manana',TRUE),(8,'pico manana',TRUE),(9,'pico manana',TRUE),
(10,'dia',FALSE),(11,'dia',FALSE),(12,'dia',FALSE),(13,'dia',FALSE),(14,'dia',FALSE),
(15,'dia',FALSE),(16,'dia',FALSE),(17,'dia',FALSE),(18,'pico tarde',TRUE),
(19,'pico tarde',TRUE),(20,'pico tarde',TRUE),(21,'pico tarde',TRUE),(22,'noche',FALSE),(23,'noche',FALSE);

CREATE TABLE IF NOT EXISTS dim_siniestro_tipo (
 siniestro_tipo_key INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tipo_siniestro VARCHAR(50) NOT NULL,
 gravedad VARCHAR(20) NOT NULL,
 tipo_usuario VARCHAR(50) NOT NULL,
 es_vulnerable BOOLEAN NOT NULL,
 UNIQUE KEY uq_tipo_dimension (tipo_siniestro,gravedad,tipo_usuario)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_siniestro (
 siniestro_id BIGINT UNSIGNED PRIMARY KEY,
 tiempo_key INT UNSIGNED NOT NULL,
 hora_key TINYINT UNSIGNED NOT NULL,
 ubicacion_key INT NOT NULL DEFAULT -1,
 siniestro_tipo_key INT UNSIGNED NOT NULL,
 num_siniestros INT UNSIGNED NOT NULL DEFAULT 1,
 num_muertos INT UNSIGNED NOT NULL DEFAULT 0,
 num_heridos INT UNSIGNED NOT NULL DEFAULT 0,
 peso_gravedad TINYINT UNSIGNED NOT NULL,
 calidad_geo VARCHAR(30) NOT NULL,
 fuente VARCHAR(50) NOT NULL,
 INDEX idx_fact_tiempo (tiempo_key),
 INDEX idx_fact_hora (hora_key),
 INDEX idx_fact_tipo (siniestro_tipo_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tipo_usuario_victima (
 id TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 nombre VARCHAR(40) NOT NULL,
 es_vulnerable BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE KEY uq_tipo_usuario_victima_nombre (nombre)
) ENGINE=InnoDB;

INSERT IGNORE INTO tipo_usuario_victima(nombre,es_vulnerable) VALUES
('peaton',TRUE),('ciclista',TRUE),('motociclista',TRUE),
('conductor',FALSE),('pasajero',FALSE),('otro',FALSE),('no_especificado',FALSE);

CREATE TABLE IF NOT EXISTS siniestro_victima (
 siniestro_id BIGINT UNSIGNED NOT NULL,
 tipo_usuario_id TINYINT UNSIGNED NOT NULL,
 num_muertos INT UNSIGNED NOT NULL DEFAULT 0,
 num_heridos INT UNSIGNED NOT NULL DEFAULT 0,
 PRIMARY KEY (siniestro_id,tipo_usuario_id),
 FOREIGN KEY (siniestro_id) REFERENCES analytics_siniestro(id) ON DELETE CASCADE,
 FOREIGN KEY (tipo_usuario_id) REFERENCES tipo_usuario_victima(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS indicador_anual (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 clave_indicador VARCHAR(100) NOT NULL,
 descripcion VARCHAR(255) NOT NULL,
 anio SMALLINT UNSIGNED NOT NULL,
 valor DOUBLE NOT NULL,
 fuente_dato VARCHAR(30) NOT NULL,
 UNIQUE KEY uq_indicador_anio (clave_indicador,anio)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS infraestructura (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 osm_id VARCHAR(100) NOT NULL,
 tipo VARCHAR(40) NOT NULL,
 latitud DOUBLE NOT NULL,
 longitud DOUBLE NOT NULL,
 tags JSON NULL,
 geometria JSON NULL,
 UNIQUE KEY uq_infra_osm_id (osm_id),
 INDEX idx_infra_tipo (tipo),
 INDEX idx_infra_ubicacion (latitud,longitud)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS limite_municipal (
 clave VARCHAR(5) PRIMARY KEY,
 geometria JSON NOT NULL,
 osm_id VARCHAR(100) NOT NULL,
 hash_archivo CHAR(64) NOT NULL
) ENGINE=InnoDB;

