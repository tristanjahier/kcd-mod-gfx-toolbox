/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 */
class BellTowerDial
{
    var m_CurrentHour;
    var m_IsMuted;
    var m_LastChime;
    var m_ManualOffset;

    function BellTowerDial()
    {
        this.m_CurrentHour = 12;
        this.m_IsMuted = false;
        this.m_LastChime = "";
        this.m_ManualOffset = 0;
    }

    function SetHour(hour)
    {
        this.m_CurrentHour = this._normalizeHour(hour + this.m_ManualOffset);
        this.m_LastChime = "Hour set: " + this.m_CurrentHour;
    }

    function ShiftDial(offset)
    {
        if (offset == undefined) {
            offset = 0;
        }

        this.m_ManualOffset = this.m_ManualOffset + offset;
        this.m_CurrentHour = this._normalizeHour(this.m_CurrentHour + offset);
        return this.m_CurrentHour;
    }

    function ToggleMute(value)
    {
        if (value == undefined) {
            this.m_IsMuted = !this.m_IsMuted;
        } else {
            this.m_IsMuted = !!value;
        }

        return this.m_IsMuted;
    }

    function Ring()
    {
        if (this.m_IsMuted) {
            this.m_LastChime = "Muted";
            return 0;
        }

        this.m_LastChime = "Bell " + this.m_CurrentHour;
        return this.m_CurrentHour == 0 ? 12 : this.m_CurrentHour;
    }

    function GetStatusText()
    {
        var muteText = this.m_IsMuted ? "MUTED" : "AUDIBLE";
        return "HOUR " + this.m_CurrentHour + " | " + muteText + " | " + this.m_LastChime;
    }

    function _normalizeHour(hour)
    {
        while (hour < 0) {
            hour = hour + 24;
        }

        while (hour >= 24) {
            hour = hour - 24;
        }

        return hour;
    }
}
