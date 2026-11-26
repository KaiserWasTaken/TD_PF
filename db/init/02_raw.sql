CREATE TABLE IF NOT EXISTS raw_catalogo_fuentes (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 fuente VARCHAR(100) NOT NULL,
 url TEXT NULL,
 formato VARCHAR(30) NULL,
 licencia VARCHAR(200) NULL,
 fecha_descarga DATETIME NULL,
 hash_sha256 CHAR(64) NULL,
 filas INT UNSIGNED NULL,
 filas_municipio INT UNSIGNED NULL,
 estatus VARCHAR(30) NULL,
 INDEX idx_catalogo_fecha (fecha_descarga)
) ENGINE=InnoDB;
