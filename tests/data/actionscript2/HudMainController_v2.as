/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 *
 * It intentionally reuses the same class name (HudMainController) while
 * changing the implementation completely. The objective is for this script not
 * to pair with its v1 counterpart; so that it produces this diff:
 *      HudMainController => CoreController  (modified, renamed)
 *      HudMainController                    (new)
 */
class HudMainController
{
    var m_Core;
    var m_SessionId;
    var m_LastBanner;
    var m_Dirty;

    function HudMainController()
    {
        this.m_Core = new CoreController();
        this.m_SessionId = "S0";
        this.m_LastBanner = "";
        this.m_Dirty = false;
    }

    function Boot(sessionId)
    {
        if (sessionId == undefined || sessionId == "") {
            sessionId = "S0";
        }

        this.m_SessionId = sessionId;
        this.m_Dirty = true;
        this.m_Core.Log("HUD boot " + sessionId);
    }

    function PushMark(id, text, distance)
    {
        this.m_Core.AddCompassMark(id, text, distance);
        this.m_LastBanner = this.m_Core.GetStatusText();
        this.m_Dirty = true;
        return this.m_LastBanner;
    }

    function Tick(delta)
    {
        this.m_Core.TickHUD(delta);
        if (this.m_Dirty) {
            this.m_LastBanner = this.m_Core.GetStatusText();
            this.m_Dirty = false;
        }

        return this.m_LastBanner;
    }

    function GetTravelHint()
    {
        this.m_Core.RefreshTravelHint();
        return this.m_Core.GetStatusText();
    }

    function DebugSnapshot()
    {
        return "[HUD " + this.m_SessionId + "] " + this.m_LastBanner;
    }
}
