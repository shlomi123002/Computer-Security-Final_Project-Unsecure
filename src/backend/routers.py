from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from schemas import ClientCreate, UserCreate, UserLogin, ForgotPasswordRequest, PasswordChangeRequest , ResetPasswordRequest
from crud import create_user, validate_user, update_password, create_client, verify_password, generate_salt, number_of_password_history
from database import get_db
from utils import send_recovery_code, recovery_code_hashed
from sqlalchemy import text
import random

user_router = APIRouter()

#SQL injection vulnerability for register page -> email : hacker@gmail.com', 'password', 'salt'); #
@user_router.post("/register/")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    try:
        result = create_user(db, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result

# SQL injection vulnerability for login page -> user name : hacker' OR 1=1 #
@user_router.post("/login/")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    try:
        validated_user = validate_user(db, user.username, user.password)
        if validated_user:
            return {"message": "Login successful"}
        else:
            raise HTTPException(status_code=400, detail="Invalid username or password")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@user_router.post("/forgot-password/")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    get_email_query = text(f"SELECT email FROM users WHERE userName = '{request.user_name}' LIMIT 1;")
    email = db.execute(get_email_query).fetchone()

    if not email:
        raise ValueError("Username not found")
    
    # Generate a 6-digit random code
    random_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    salt = generate_salt()

    recovery_code_with_sha1 = recovery_code_hashed(str(random_code), str(salt))

    userID_query = text(f"SELECT userID FROM users WHERE userName = '{request.user_name}'")
    userID_Result = db.execute(userID_query).fetchone()

    userID = userID_Result[0]

    delete_recovery_code_query = text(f"DELETE FROM recovery_code WHERE userID = {userID}")
    db.execute(delete_recovery_code_query)
    db.commit()

    # Insert recovery code (this part uses parameterized query)
    insert_recovery_code_query = text(f"""
        INSERT INTO recovery_code (userID, recovery_code, salt)
        VALUES ('{userID}', '{recovery_code_with_sha1}', '{salt}')
    """)
    db.execute(insert_recovery_code_query)

    db.commit()

    send_recovery_code(email[0], random_code)
    
    return {"msg": "Recovery code sent to your email"}

@user_router.post("/reset-password/")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    userID_query = text(f"SELECT userID FROM users WHERE userName = '{request.user_name}'")
    userID_result = db.execute(userID_query).fetchone()
    user_id = userID_result[0]

    recovery_code_query = text(f"SELECT recovery_code, salt FROM recovery_code WHERE userID = '{user_id}'")
    result = db.execute(recovery_code_query).fetchone()

    table_recovery_code = result[0]
    recovery_code_salt = result[1]

    current_recovery_code = recovery_code_hashed(str(request.recovery_code), str(recovery_code_salt))

    if current_recovery_code != table_recovery_code:
        raise HTTPException(status_code=400, detail="Invalid recovery code")
    
    # Update the password
    update_password(db, request.user_name, request.new_password)
    return {"msg": "Password reset successful"}

@user_router.put("/change-password/")
def change_password(user: PasswordChangeRequest, db: Session = Depends(get_db)):
    # Verify current password
    if not verify_password(db, user.current_password, user.user_name):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    number_of_history = number_of_password_history()

    if not update_password(db, user.user_name, user.new_password):
        raise HTTPException(status_code=400, detail=f"The new password cannot be one of the last '{number_of_history}' used passwords.")
    
    return {"msg": "Password updated successfully"}

#XSS attack : <img src="x" onerror="window.location=\'https://www.hit.ac.il/\'">
#SQL injection vulnerability for dashboard page -> client name :  hacker' , 'Sqli' , 'hacker@gmail.com' , '0' );#
@user_router.post("/Dashboard/")
def add_client(client: ClientCreate, db: Session = Depends(get_db)):
    try:
        create_client(db, client)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"msg": "Client added successfully"}

@user_router.get("/client-table")
def get_clients(db: Session = Depends(get_db)):
    try:
        query = text("SELECT * FROM clients")
        result = db.execute(query)
        clients = result.fetchall()

        if not clients:
            raise HTTPException(status_code=404, detail="No clients found")
        
        client_list = []
        for row in clients:
            clientID = row["clientID"]

            package_query = text(f"SELECT * FROM internet_packages WHERE client_id = '{clientID}'")
            packages = db.execute(package_query)

            for package_info in packages:
                package_information = f"{package_info['name']} ,speed: {package_info['speed']}, Data Limit: {package_info['data_limit']}, price: {package_info['price']}"

                sector_query = text(f"SELECT name FROM sectors WHERE client_id = '{clientID}'")
                sector = db.execute(sector_query).fetchone()

                client_list.append({
                    "clientFirstName": row["clientFirstName"],
                    "clientLastName": row["clientLastName"],
                    "clientEmail": row["clientEmail"],
                    "clientPhoneNumber": row["clientPhoneNumber"],
                    "selectedPackage": package_information,
                    "selectedSector": sector["name"] ,
                    "clientID" : clientID
                })

        return client_list
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
# New DELETE endpoint to delete a client
@user_router.delete("/clients/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    try:
        # Check if the client exists
        client_query = text("SELECT * FROM clients WHERE clientID = :client_id")
        client = db.execute(client_query, {"client_id": client_id}).fetchone()

        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Delete associated internet packages
        delete_packages_query = text("DELETE FROM internet_packages WHERE client_id = :client_id")
        db.execute(delete_packages_query, {"client_id": client_id})

        # Delete associated sectors
        delete_sectors_query = text("DELETE FROM sectors WHERE client_id = :client_id")
        db.execute(delete_sectors_query, {"client_id": client_id})

        # Delete the client
        delete_client_query = text("DELETE FROM clients WHERE clientID = :client_id")
        db.execute(delete_client_query, {"client_id": client_id})

        db.commit()
        
        return {"msg": "Client deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error")