/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 *
 * It is a rename of HudMainController with a few modifications.
 */
class CoreController
{
    var m_PlayerName;
    var m_Stamina;
    var m_CompassMarks;
    var m_FastTravelUnlocked;
    var m_Log;

    function CoreController()
    {
        this.m_PlayerName = "Henry";
        this.m_Stamina = 100;
        this.m_CompassMarks = new Array();
        this.m_FastTravelUnlocked = false;
        this.m_Log = new Array();
    }

    function SetPlayerName(name)
    {
        this.m_PlayerName = name;
        this.Log("Player renamed to " + name);
    }

    function AddCompassMark(id, label, distance)
    {
        var safeLabel = label;
        if (safeLabel == undefined || safeLabel == "") {
            safeLabel = "Marker " + id;
        }

        var mark = { id : id, label : safeLabel, distance : distance };
        this.m_CompassMarks.push(mark);
        this.Log("Compass mark added: " + safeLabel);
    }

    function TickHUD(delta)
    {
        this.m_Stamina = this.m_Stamina - delta;
        if (this.m_Stamina < 0) {
            this.m_Stamina = 0;
        }

        if (this.m_Stamina > 82 && this.m_CompassMarks.length > 2) {
            this.m_FastTravelUnlocked = true;
        } else {
            this.m_FastTravelUnlocked = false;
        }
    }

    function GetStatusText()
    {
        var mode = this.m_FastTravelUnlocked ? "READY" : "LOCKED";
        return this.m_PlayerName + " | STA " + this.m_Stamina + " | FAST TRAVEL " + mode;
    }

    function RefreshTravelHint()
    {
        if (this._canShowTravelHint()) {
            this.Log("Travel hint ready");
        } else {
            this.Log("Travel hint waiting");
        }
    }

    function _canShowTravelHint()
    {
        return this.m_CompassMarks.length > 0 && this.m_Stamina > 20;
    }

    function Log(message)
    {
        this.m_Log.push(message);
        if (this.m_Log.length > 8) {
            this.m_Log.shift();
        }
    }
}
