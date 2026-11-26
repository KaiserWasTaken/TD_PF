CREATE TABLE IF NOT EXISTS mart_autoridades_kpi_resumen (
 id TINYINT UNSIGNED PRIMARY KEY,
 total_siniestros INT UNSIGNED NOT NULL,
 muertos INT UNSIGNED NOT NULL,
 heridos INT UNSIGNED NOT NULL,
 actualizado DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS mart_ciudadania_siniestros_publicos (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 fecha_hora DATETIME NULL,
 tipo_siniestro VARCHAR(50) NULL,
 tipo_usuario VARCHAR(50) NULL,
 gravedad VARCHAR(20) NULL,
 latitud DECIMAL(8,5) NULL,
 longitud DECIMAL(9,5) NULL,
 INDEX idx_publicos_fecha (fecha_hora)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS mart_ciudadania_tramos_riesgo (
 tramo_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 nombre_vialidad VARCHAR(150) NOT NULL,
 longitud_m DOUBLE NOT NULL DEFAULT 0,
 indice_riesgo DECIMAL(8,5) NOT NULL DEFAULT 0,
 siniestros INT UNSIGNED NOT NULL DEFAULT 0,
 lat_inicio DOUBLE NULL,
 lon_inicio DOUBLE NULL,
 lat_fin DOUBLE NULL,
 lon_fin DOUBLE NULL
) ENGINE=InnoDB;
