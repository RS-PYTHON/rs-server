import psycopg2

class CADIPDBPlugin():
    def __init__(self) -> None:
        self.table_name = 'public."CADU_status"'
        self.db_connect()
    
    def __del__(self) -> None:
        self.connection.close()
        
    def db_connect(self):
        self.connection = psycopg2.connect(database = "CADIP", 
                            user = "postgres", 
                            host= 'localhost',
                            password = "test",
                            port = 5432)
        
    def insert_status(self, status_dict: dict) -> None:
        """Example = {"identifier" : "A",
        "name": "B", 
        "available_at_station_date": "C",
        "download_start_date": "D",
        "download_stop_date": "E",
        "status": "F",
        "status_failed_detailed": "GH"}
        """
        columns = ', '.join(status_dict.keys())
        values = ', '.join([f"'{value}'" for value in status_dict.values()])
        sql_query = f"INSERT INTO {self.table_name} ({columns}) VALUES ({values});"
        cursor = self.connection.cursor()
        cursor.execute(sql_query)
        self.connection.commit()

    def print_db(self):
        cursor = self.connection.cursor()
        cursor.execute('SELECT * FROM public."CADU_status"')
        rows = cursor.fetchall()
        for row in rows:
            print(row)
        cursor.close()

    def select_value(self, value_dict):
        """
            Example = {"Identifier" : "A"}
        """
        condition = [f"{key}='{value}'" for key, value in value_dict.items()]
        sql_query = f"SELECT * FROM {self.table_name} WHERE {condition[0]};"
        cursor = self.connection.cursor()
        cursor.execute(sql_query)
        self.connection.commit()
        return cursor.fetchall()

    def update_db(self, id, value_dict):
        value = {}
        sql_query = f"UPDATE {self.table_name} SET {value} WHERE identifier='{id}';"


# def db_connect():
#     conn = psycopg2.connect(database = "CADIP", 
#                         user = "postgres", 
#                         host= 'localhost',
#                         password = "test",
#                         port = 5432)
#     return conn

# def insert_status(connection, status_dict: dict) -> None:
#     """Example = {"identifier" : "A",
#     "name": "B", 
#     "available_at_station_date": "C",
#     "download_start_date": "D",
#     "download_stop_date": "E",
#     "status": "F",
#     "status_failed_detailed": "GH"}
#     """
#     table_name = 'public."CADU_status"'
#     columns = ', '.join(status_dict.keys())
#     values = ', '.join([f"'{value}'" for value in status_dict.values()])
#     sql_query = f"INSERT INTO {table_name} ({columns}) VALUES ({values});"
#     cursor = connection.cursor()
#     cursor.execute(sql_query)
#     connection.commit()

# def print_db(connection):
#     cursor = connection.cursor()
#     cursor.execute('SELECT * FROM public."CADU_status"')
#     rows = cursor.fetchall()
#     for row in rows:
#         print(row)
#     cursor.close()

# def select_value(connection, value_dict):
#     """
#     Example = {"Identifier" : "A"}
#     """
#     table_name = 'public."CADU_status"'
#     condition = [f"{key}='{value}'" for key, value in value_dict.items()]
#     sql_query = f"SELECT * FROM {table_name} WHERE {condition[0]};"
#     cursor = connection.cursor()
#     cursor.execute(sql_query)
#     connection.commit()
#     return cursor.fetchall()


if __name__ == "__main__":
    obj = CADIPDBPlugin()
    inser = {"identifier" : "wdsssss",
        "name": "B", 
        "available_at_station_date": "C",
        "download_start_date": "D",
        "download_stop_date": "E",
        "status": "F",
        "status_failed_detailed": "GH"}
    obj.print_db()
    obj.insert_status(inser)
    obj.print_db()
    print(obj.select_value({"identifier" : "A"}))