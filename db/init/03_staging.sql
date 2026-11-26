CREATE TABLE IF NOT EXISTS staging_siniestro_rechazado (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 id_origen VARCHAR(100) NULL,
 motivo_rechazo VARCHAR(255) NOT NULL,
 registro JSON NULL,
 fecha_rechazo DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_rechazado_origen (id_origen)
) ENGINE=InnoDB;
