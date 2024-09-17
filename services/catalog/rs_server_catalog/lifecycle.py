import psycopg2


# Function to detect expired items
def check_expired_items(database_url):

    # Connect to the database
    try:
        connection = psycopg2.connect(database_url)
        cursor = connection.cursor()

        # Define the SQL query to retrieve the collection with id 'toto_S1_L1'
        query = """
                SELECT *
                FROM items
                WHERE (content->'properties'->>'expires')::timestamptz < now()
                """

        cursor.execute(query, ("toto_S1_L1",))

        # Fetch all results
        expired_items = cursor.fetchall()

        return expired_items

    except Exception as e:
        print(f"Error checking expired items: {e}")
    finally:
        # Close the connection
        if connection:
            cursor.close()
            connection.close()
