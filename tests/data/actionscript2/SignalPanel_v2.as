/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 *
 * In this version, the method order has been completely reversed.
 */
class SignalPanel
{
    var m_IsVisible;
    var m_CurrentMode;
    var m_Entries;
    var m_LastMessage;

    function _sortEntriesByPriority()
    {
        this.m_Entries.sort(
            function (a, b) {
                if (a.priority == b.priority) {
                    return 0;
                }

                return a.priority > b.priority ? -1 : 1;
            }
        );
    }

    function BuildSummary()
    {
        var state = this.m_IsVisible ? "VISIBLE" : "HIDDEN";
        return state + " | " + this.m_CurrentMode + " | ENTRIES " + this.m_Entries.length + " | " + this.m_LastMessage;
    }

    function RemoveEntry(id)
    {
        var i;
        for (i = 0; i < this.m_Entries.length; i++) {
            if (this.m_Entries[i].id == id) {
                this.m_Entries.splice(i, 1);
                this.m_LastMessage = "Entry removed: " + id;
                return true;
            }
        }

        return false;
    }

    function AddEntry(id, text, priority)
    {
        var entryText = text;
        if (entryText == undefined || entryText == "") {
            entryText = "Untitled";
        }

        var entryPriority = priority;
        if (entryPriority == undefined || entryPriority < 0) {
            entryPriority = 0;
        }

        var entry = { id : id, text : entryText, priority : entryPriority };
        this.m_Entries.push(entry);
        this._sortEntriesByPriority();
        this.m_LastMessage = "Entry added: " + entryText;
    }

    function SetMode(mode)
    {
        if (mode == undefined || mode == "") {
            mode = "Normal";
        }

        this.m_CurrentMode = mode;
        this.m_LastMessage = "Mode switched: " + mode;
    }

    function SetVisible(value)
    {
        this.m_IsVisible = !!value;
        this.m_LastMessage = this.m_IsVisible ? "Panel visible" : "Panel hidden";
    }

    function SignalPanel()
    {
        this.m_IsVisible = true;
        this.m_CurrentMode = "Normal";
        this.m_Entries = new Array();
        this.m_LastMessage = "";
    }
}
