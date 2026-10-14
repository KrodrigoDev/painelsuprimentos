"""
(Movido para o ETL) O catálogo de equivalências agora é processado no airflow_api_sienge:

    python main.py --etapa inteligencia_compras        # na pasta repo do airflow_api_sienge
    (ou DAG etl_inteligencia_compras / etl_pedidos_compra no Airflow)
"""
import sys

if __name__ == "__main__":
    print(__doc__)
    sys.exit(1)
