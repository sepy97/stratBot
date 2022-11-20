# Import the client
from td.client import TDClient

def initTDSession():
    # Create a new session, credentials path is required.
    TDSession = TDClient(
        client_id='DLGHTG07LAMJSNLDPD0VGAHEZJZVTMYD',
        redirect_uri='http://127.0.0.1',
        credentials_path='/Users/ilya/Git/StratBot_Sema/td_state.json'
    )
    # Login to the session
    TDSession.login()
    return TDSession

